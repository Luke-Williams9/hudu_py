# From https://github.com/TelcoCentric/hudu_py

# This can be in the bind mount folder for now, so we don't have to rebuild the Docker image every time I change something
# from scripts.huduapi import Hudu


import datetime
import requests
import json
from enum import Enum
import os
import time
import logging
from logger import NullHandler, HideSensitiveFilter, HideSensitiveService

null_handler = NullHandler()
logger = logging.getLogger(__name__)
logger.addHandler(null_handler)
logger.addFilter(HideSensitiveFilter())


class Hudu(object):

    class FieldType(Enum):
        TEXT = 'Text'
        RICHTEXT = 'RichText'
        HEADING = 'Heading'
        CHECKBOX = 'CheckBox'
        WEBSITE = 'Website'
        PASSWORD = 'Password'
        EMAIL = 'Email'
        NUMBER = 'Number'
        DATE = 'Date'
        DROPDOWN = 'Dropdown'
        EMBED = 'Embed'
        PHONE = 'Phone'
        ASSETLINK = 'AssetLink'
        ASSETTAG = 'AssetTag'

    class Field():
        def __init__(self, label: str, show_in_list: bool, required: bool, field_type: Enum, min: int = None, max: int = None, hint: str = None, options: str = None, position: int = None, expiration: bool = False, linkable_id: int = None):
            self.label = label
            self.min = min
            self.max = max
            self.show_in_list = show_in_list
            self.required = required
            self.field_type = field_type.value
            self.hint = hint
            self.options = options
            self.posistion = position
            self.expiration = expiration
            self.linkable_id = linkable_id

    def __init__(self, api_key=None, domain=None, api_version=None, lookupTables = False):
        # API key can only be defined on object creation. If no key found, then do not proceed
        if api_key is None: api_key = os.environ.get('HUDU_API_KEY', None)
        if api_key is None:
            # If we are in Docker, check for a secret
            defaultSecret = '/run/secrets/HUDU_API_KEY'
            if os.path.exists(defaultSecret):
                with open(defaultSecret, "r") as file:
                    api_key = file.read().strip()
        if api_key is None: 
            raise ValueError("No api_key found. please either specify api_key as a parameter, define it as an environment variable or secret called 'HUDU_API_KEY'")
        if domain is None: 
            domain = os.environ.get('HUDU_DOMAIN', None)
        if api_version is None: 
            api_version = os.environ.get('HUDU_API_VERSION', "v1")
        
        self.__pageSize = 25

        self.headers = {
            "accept":       'application/json',
            "Content-Type": 'application/json',
            "x-api-key":    api_key
        }
        
        self.domain = domain
        self.api_version = api_version
        url = f'https://{domain}/api/{api_version}'
        self.url = url
        # Add lookup tables
        logger.debug('Create lookup tables:')

        if lookupTables is True:
            for item in ['companies', 'asset_layouts']:
                logger.debug(item)
                temp_raw = self.do_request('GET',item)
                lookup_table = {}
                for c in temp_raw:
                    lookup_table[c['name']] = c['id']
                    lookup_table[c['id']] = c['name']
                setattr(self,item,lookup_table)
            temp_raw = None
                
    def do_raw_get(self, endpoint=None, params={}):
        # For troubleshooting and data format examination more than anything
        URI = f'{self.url}/{endpoint}'
        response = requests.get(URI, headers=self.headers, params=params)
        return response

    def do_request(self, method: str = 'GET', endpoint=None, p={}):
        # p can be used for params or data, depending on the call
        result = None
        methods = ['GET','POST','PUT','DELETE']
        if method not in methods:
            raise ValueError(f'Please specify HTTP method: {", ".join(methods)}')
        if endpoint is None:
            raise ValueError('Please specify endpoint.')
        
        URI = f'{self.url}/{endpoint}'
        logger.debug(f'{method}: {URI}')
        logger.debug(f'p: {p}')
        match method:
            case 'GET':
                # Deal with Hudu APIs pagination
                # Try 1000 page_size first. Some GET endpoints don't support page_size
                result = []
                p['page'] = 1
                p['page_size'] = 1000
                response_size = p['page_size']

                # for put and post: -H 'Content-Type: application/json' 
                while response_size >= p['page_size']:
                    # try:
                    #     logger.debug(json.dumps(p))
                    # except:
                    #     logger.debug(p)
                    logger.debug(f"response_size: {response_size}  ---  page_size: {p['page_size']}")
                    response = requests.get(URI, headers=self.headers, params=p)
                    time.sleep(0.01)
                    # There's a bug in here somewhere, pulling individual assets doesn't always work
                    match response.status_code:
                        case 200:
                            # Response OK 
                            r_json = response.json()
                            match type(r_json).__name__: 
                                case 'dict':
                                    # when the response is wrapped in a named object, it will be the only/first object in the response
                                        # when getting single assets, the returned type is 'response' ...?
                                    key_name = list(r_json.keys())[0]
                                    r_data = r_json[key_name]
                                case 'list':
                                    # when the response is just a list, we can pass it through
                                    r_data = r_json
                                case _:
                                    # Just in case there are any other types of responses I haven't accounted for...
                                    raise ValueError(f"I'm not set up to handle this type: {type(r_json)}")
                            if type(r_data) is dict:
                                # at this point, if our result is a dict, then it is just one item being returned
                                response_size = 1
                                result = [ r_data ]
                            else:
                                # if its not a dict, it'll be a list of items
                                response_size = len(r_data)
                                result += r_data
                            #if len(r_data) > 0:
                            # If the endpoint doesn't support page_size, and it returns exactly 25 results, set the page_size to 25
                            if response_size == 25:
                                p['page_size'] = 25
                            p['page'] += 1
                        case 429:
                            # too many requests, sleep for a bit
                            time.sleep(30)
                        case _:
                            err_str = f'Error {response.status_code}'
                            if hasattr(response, 'reason'):
                                err_str += f' --- {response.reason}'
                            raise ValueError(err_str)
            case ('PUT' | 'POST' | 'DELETE'):
                match method:
                    case ('PUT' | 'POST'):
                        body = json.dumps(p)
                        logger.debug(f'Body: {body}')
                        match method:
                            case 'PUT':
                                response = requests.put(URI, headers=self.headers, data=body)
                            case 'POST':
                                response = requests.post(URI, headers=self.headers, data=body)
                    case 'DELETE':
                        response = requests.delete(URI, headers=self.headers)

                logger.debug(f'response: {response}')
                
                try:
                    result = response.json()
                except:
                    result = response
        return result

    ###
    # Activity logs
    ###

    def get_activity_logs(self, user_id: int = None, user_email: str = None, resource_id: int = None, resource_type: str = None, action_message: str = None, start_date: datetime = None):
        params = {}

        if resource_id is not None and resource_type is None:
            # REE
            resource_id = None
            message = "resource id. Must be coupled with resource_type"
        if resource_type is not None and resource_id is None:
            # ALSO REE
            resource_type = None
            message = "resource type (Asset, AssetPassword, Company, Article, etc.). Must be coupled with resource_id"
        
        if user_id is not None: params['user_id'] = user_id
        if user_email is not None: params['user_email'] = user_email
        if resource_id is not None: params['resource_id'] = resource_id
        if resource_type is not None: params['resource_type'] = resource_type
        if action_message is not None: params['action_message'] = action_message
        if start_date is not None: params['start_date'] = start_date.isoformat() #Must be in ISO 8601 format

        return self.do_request('GET','activity_logs', params)

    ###
    # Api info
    ###

    def get_api_info(self):
        return self.do_request('GET','api_info')

    ###
    # ARTICLES
    ###
    def get_articles(self, name: str = None, company_id: int = None, draft: bool = None):
        params = {}

        if name is not None: params['name'] = name
        if company_id is not None: params['company_id'] = company_id
        if draft is not None: params['draft'] = draft

        return self.do_request('GET','articles',params)

    def get_article(self, id):
        return self.do_request('GET',f'articles/{id}',params)

    def create_article(self, name: str, content: str, enable_sharing: bool = None, folder_id: int = None, company_id: int = None):
        data = {
            'article': {}
        }

        data['article']['name'] = name
        data['article']['content'] = content
        if enable_sharing is not None: data['article']['enable_sharing'] = enable_sharing
        if folder_id is not None: data['article']['folder_id'] = folder_id
        if company_id is not None: data['article']['company_id'] = company_id
        
        return self.do_request('POST',f'articles',data)
            
    def update_article(self, id: int, name: str, content: str, enable_sharing: bool = None, folder_id: int = None, company_id: int = None):
        data = {
            'article': {}
        }

        data['article']['name'] = name
        data['article']['content'] = content
        if enable_sharing is not None: data['article']['enable_sharing'] = enable_sharing
        if folder_id is not None: data['article']['folder_id'] = folder_id
        if company_id is not None: data['article']['company_id'] = company_id
        return self.do_request('PUT',f'articles/{id}',data)
        
    def remove_article(self, id):
        return self.do_request('DELETE',f'articles/{id}')
    
    def archive_article(self, id):
        return self.do_request('PUT',f'articles/{id}/archive')
        
    def unarchive_article(self, id):
        return self.do_request('PUT',f'articles/{id}/unarchive')

    ###
    # Asset layouts
    ###

    def get_asset_layouts(self, name: str = None):
        params = {}
        if name is not None: params['name'] = name
        return self.do_request('GET','asset_layouts',params)
        
    def get_asset_layout(self, id: int):
        return self.do_request('GET',f'asset_layouts/{id}',params)
        
    ## Fields to be list of dict
    def create_asset_layouts(self, name: str, icon: str, color: str, icon_color: str,  fields: list[dict], include_passwords: bool = None, include_photos: bool = None, include_comments: bool = None, include_files: bool = None, password_types: str = None):
        data = {
            'asset_layout': {}
        }

        data['asset_layout']['name'] = name
        data['asset_layout']['icon'] = icon
        data['asset_layout']['color'] = color
        data['asset_layout']['icon_color'] = icon_color
        if include_passwords is not None: data['asset_layout']['include_passwords'] = include_passwords
        if include_photos is not None: data['asset_layout']['include_photos'] = include_photos
        if include_comments is not None: data['asset_layout']['include_comments'] = include_comments
        if include_files is not None: data['asset_layout']['include_files'] = include_files
        if password_types is not None: data['asset_layout']['password_types'] = password_types

        data['asset_layout']['fields'] = []
        for field in fields:
            data['asset_layout']['fields'].append(field.__dict__)
        
        return self.do_request('POST','asset_layouts',data)
        
            
    def update_asset_layouts(self, id: int, name: str, icon: str, color: str, icon_color: str,  fields: list[dict], include_passwords: bool = None, include_photos: bool = None, include_comments: bool = None, include_files: bool = None, password_types: str = None):
        data = {
            'asset_layout': {}
        }

        data['asset_layout']['name'] = name
        data['asset_layout']['icon'] = icon
        data['asset_layout']['color'] = color
        data['asset_layout']['icon_color'] = icon_color
        if include_passwords is not None: data['asset_layout']['include_passwords'] = include_passwords
        if include_photos is not None: data['asset_layout']['include_photos'] = include_photos
        if include_comments is not None: data['asset_layout']['include_comments'] = include_comments
        if include_files is not None: data['asset_layout']['include_files'] = include_files
        if password_types is not None: data['asset_layout']['password_types'] = password_types

        data['asset_layout']['fields'] = []
        for field in fields:
            data['asset_layout']['fields'].append(field.__dict__)
        
        return self.do_request('PUT',f'asset_layouts/{id}',data)

    ###
    # Asset passwords
    ###
    def get_asset_passwords(self, name: str = None, company_id: int = None, slug: str = None, search: str = None):
        params = {}
        if name is not None: params['name'] = name
        if company_id is not None: params['company_id'] = company_id
        if slug is not None: params['slug'] = slug
        if search is not None: params['search'] = search

        return self.do_request('GET','asset_passwords',params)
    
    def get_asset_password(self, id: int):
        # when getting individual passwords or assets, we should look up their relations and include them as well

        return self.do_request('GET',f'asset_passwords/{id}')
    
    def create_asset_password(self, name: str, username: str, password: str, passwordable_type: str, otp_secret: str, url: str, password_type: str, slug: str, company_id: int, description: str = None, passwordable_id: int = 0, in_portal: bool = True, password_folder_id: int = 0):
        optional_args = ['description','passwordable_type','passwordable_id','in_portal','otp_secret','url','password_type','password_folder_id','slug']
        # define required params
        data = {
            'asset_password': {
                'name': name,
                'username': username,
                'password': password,
                'company_id': company_id
            }
        }
        # loop through optional params, add any that have been defined
        for arg in optional_args:
            if hasattr(locals(),arg):
                data[arg] = getattr(locals(),arg)

        return self.do_request('POST','asset_passwords',data)

    ###
    # Assets
    ###

    def get_assets(self, company_id: int = None, id: int = None, name: str = None, primary_serial: int = None, asset_layout_id: int = None, archived: bool = False):
        params = {}

        if company_id is not None and id is None and name is None and primary_serial is None and asset_layout_id is None:
            return self.get_company_assets(company_id=company_id, page=page, archived=archived, page_size=page_size)

        if company_id is not None: params['company_id'] = company_id
        if id is not None: params['id'] = id
        if name is not None: params['name'] = name
        if primary_serial is not None: params['primary_serial'] = primary_serial
        if asset_layout_id is not None: params['asset_layout_id'] = asset_layout_id
        if archived is not None: params['archived'] = archived
        
        return self.do_request('GET','assets',params)

    def get_company_assets(self, company_id: int = None, archived: bool = False):
        params = {}

        if company_id is not None: params['company_id'] = company_id
        if archived is not None: params['archived'] = archived

        return self.do_request('GET',f'companies/{company_id}/assets',params)
        
    def get_company_asset(self, company_id: int, id: int):
        # When looking up single assets, lets include its relations
        data = self.do_request('GET',f'companies/{company_id}/assets/{id}') 
        # all_relations = self.do_request('GET','relations')

        # # Get all its relations
        # relations = []
        # # count = 0
        # for a in all_relations:
        #     # print(count)
        #     # count += 1
        #     # print(type(a['toable_id']))
        #     # print(type(a['fromable_id']))
        #     # print(type(asset['id']))
        #     if a['toable_id'] == asset['id']:
        #         relations.append(a)
        #     if a['fromable_id'] == asset['id']:
        #         relations.append(a)
        
        # Get its passwords
        # passwordable_id is the id of the password parent asset
        all_passwords = self.do_request('GET','asset_passwords',{'company_id':company_id})
        passwords = []
        for p in all_passwords:
            if p['passwordable_id'] == id:
                passwords.append(p)

        # result = dict(**data, **passwords)
        result = {
            'data': data,
            'passwords': passwords
        }    
        return result

    def create_asset(self, company_id: int, asset_layout_id: int,  name: str, primary_serial:str = None, primary_mail: str = None, primary_model: str = None, primary_manufacturer: str = None, custom_fields: dict = None):
        data = {
            'asset': {}
        }
        
        data['asset']['asset_layout_id'] = asset_layout_id
        data['asset']['name'] = name        
        if primary_serial is not None: data['asset']['primary_serial'] = primary_serial
        if primary_mail is not None: data['asset']['primary_mail'] = primary_mail
        if primary_model is not None: data['asset']['primary_model'] = primary_model
        if primary_manufacturer is not None: data['asset']['primary_manufacturer'] = primary_manufacturer
        if custom_fields is not None: data['asset']['custom_fields'] = custom_fields
        
        return self.do_request('POST',f'companies/{company_id}/assets',data)
            
    def update_asset(self, id: int, company_id: int, asset_layout_id: int = None, name: str = None, primary_serial:str = None, primary_mail: str = None, primary_model: str = None, primary_manufacturer: str = None, custom_fields: dict = None):
        data = {
            'asset': {}
        }
        # get the name and the asset layout.... why does the api require these again?
        # may need to add even more
        if name is None or asset_layout_id is None:
            a = self.do_request('GET','assets',{'id': id, 'company_id': company_id})[0]
            name = a['name']
            asset_layout_id = a['asset_layout_id']
        data['asset']['asset_layout_id'] = asset_layout_id
        data['asset']['name'] = name        
        if primary_serial is not None: data['asset']['primary_serial'] = primary_serial
        if primary_mail is not None: data['asset']['primary_mail'] = primary_mail
        if primary_model is not None: data['asset']['primary_model'] = primary_model
        if primary_manufacturer is not None: data['asset']['primary_manufacturer'] = primary_manufacturer
        if custom_fields is not None: 
            parsed_data = []
            for key, value in custom_fields.items():
                new_key = key.lower().replace(" ", "_")
                parsed_data.append({new_key: value})    
    
            data['asset']['custom_fields'] = parsed_data
        
        

        return self.do_request('PUT',f'companies/{company_id}/assets/{id}',data)

    def remove_asset(self, id: int, company_id: int):
        return self.do_request('DELETE',f'companies/{company_id}/assets/{id}')
    
    def archive_asset(self, id: int, company_id: int):
        return self.do_request('PUT',f'companies/{company_id}/assets/{id}/archive')
        
    def unarchive_assets(self, id: int, company_id: int):
        return self.do_request('PUT',f'companies/{company_id}/assets/{id}/unarchive')

    ###
    # Cards
    ###

    ###
    # Companies
    ###

    ###
    # Expirations
    ###

    ###
    # Folders
    ###

    ###
    # Magic dash
    ###

    ###
    # Procedures
    ###

    ###
    # Relations
    ###

    ###
    # Websites
    ###
